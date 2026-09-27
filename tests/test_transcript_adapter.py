"""Tests for skillc/transcript_adapter.py (#106, split 1 of 2).

Every fixture consumed here is hand-built, entirely synthetic, and matches
a REAL client transcript shape observed on this host - see each fixture
directory's own README for exactly what was confirmed and how.

These tests exercise the SAME `verify_first_user_message`/`check_canary`
functions #78 already ships and already tests against synthetic event
lists (`tests/test_trial_bootstrap.py`) - this file proves the ADAPTER
produces events those functions accept, never re-tests their own logic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillc import transcript_adapter as ta
from skillc.trial_bootstrap import (
    CanaryNotSatisfied,
    PromptDeliveryError,
    check_canary,
    verify_first_user_message,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transcripts"

CLAUDE_NONCE = "aaaa1111bbbb2222"
CODEX_NONCE = "cccc3333dddd4444"
PROMPT_FOR_NONCE = {
    CLAUDE_NONCE: (
        "Invoke the demo-skill skill, then use a tool to write the exact text "
        f"'touched:{CLAUDE_NONCE}' to a file named 'skillc-canary-{CLAUDE_NONCE}.txt' in the working directory."
    ),
    CODEX_NONCE: (
        "Invoke the demo-skill skill, then use a tool to write the exact text "
        f"'touched:{CODEX_NONCE}' to a file named 'skillc-canary-{CODEX_NONCE}.txt' in the working directory."
    ),
}


def _read(client: str, name: str) -> str:
    return (FIXTURES / client / f"{name}.jsonl").read_text(encoding="utf-8")


# --------------------------------------------------------------- Claude Code

def test_claude_code_live_canary_satisfies_prompt_delivery_and_canary() -> None:
    events = ta.parse_claude_code_transcript(_read("claude-code", "live-canary"))
    verify_first_user_message(events, PROMPT_FOR_NONCE[CLAUDE_NONCE])  # must not raise
    check_canary(events, "demo-skill", CLAUDE_NONCE)  # must not raise


def test_claude_code_red_case_tool_call_requested_but_fails() -> None:
    """#106's own acceptance: red when a tool call is requested but fails."""
    events = ta.parse_claude_code_transcript(_read("claude-code", "tool-call-fails"))
    verify_first_user_message(events, PROMPT_FOR_NONCE[CLAUDE_NONCE])  # prompt delivery is unaffected
    with pytest.raises(CanaryNotSatisfied):
        check_canary(events, "demo-skill", CLAUDE_NONCE)


def test_claude_code_red_case_no_op_transcript() -> None:
    """#106's own acceptance: red on a no-op transcript."""
    events = ta.parse_claude_code_transcript(_read("claude-code", "no-op"))
    with pytest.raises(CanaryNotSatisfied):
        check_canary(events, "demo-skill", CLAUDE_NONCE)


def test_claude_code_adapter_never_emits_an_event_for_an_unconfirmed_tool_call() -> None:
    """An unmatched tool_use (no tool_result anywhere) must contribute no
    tool_use event at all - not one with `error=True` fabricated, since
    this module never invents a result the transcript does not contain."""
    raw = _read("claude-code", "live-canary")
    # Strip the skill tool_result line so toolu_skill0001 is left unconfirmed.
    lines = [ln for ln in raw.splitlines() if '"tool_use_id": "toolu_skill0001"' not in ln]
    events = ta.parse_claude_code_transcript("\n".join(lines))
    tool_use_events = [e for e in events if e.get("type") == "tool_use"]
    assert len(tool_use_events) == 1  # only the bash write call remains confirmed
    # The skill_invocation event still fires - it is a request signal, not a confirmed one.
    assert any(e.get("type") == "skill_invocation" and e.get("skill") == "demo-skill" for e in events)


# --------------------------------------------------------------------- Codex

def test_codex_live_canary_satisfies_prompt_delivery_and_canary() -> None:
    events = ta.parse_codex_transcript(_read("codex", "live-canary"))
    verify_first_user_message(events, PROMPT_FOR_NONCE[CODEX_NONCE])  # must not raise
    check_canary(events, "demo-skill", CODEX_NONCE)  # must not raise


def test_codex_red_case_tool_call_requested_but_fails() -> None:
    """#106's own acceptance: red when a tool call is requested but fails."""
    events = ta.parse_codex_transcript(_read("codex", "tool-call-fails"))
    verify_first_user_message(events, PROMPT_FOR_NONCE[CODEX_NONCE])
    with pytest.raises(CanaryNotSatisfied):
        check_canary(events, "demo-skill", CODEX_NONCE)


def test_codex_red_case_no_op_transcript() -> None:
    """#106's own acceptance: red on a no-op transcript."""
    events = ta.parse_codex_transcript(_read("codex", "no-op"))
    with pytest.raises(CanaryNotSatisfied):
        check_canary(events, "demo-skill", CODEX_NONCE)


def test_codex_adapter_skips_the_environment_context_wrapper_as_the_first_user_message() -> None:
    """The harness-injected `<environment_context>` message must never be
    read as the delivered prompt - a real Codex transcript's first `user`
    message is always this wrapper, confirmed on three live probes, and a
    prompt-delivery check that compared against it would refuse every
    real Codex trial."""
    events = ta.parse_codex_transcript(_read("codex", "live-canary"))
    first_user = next(e for e in events if e.get("role") == "user")
    assert first_user["content"] == PROMPT_FOR_NONCE[CODEX_NONCE]
    with pytest.raises(PromptDeliveryError):
        verify_first_user_message(events, "<environment_context>this is not the real prompt</environment_context>")


def test_codex_exec_output_as_a_bare_string_is_still_read() -> None:
    """Observed in one of three live probes: `output` is sometimes a plain
    string rather than a list of blocks. Both shapes must parse the same
    way, or a real transcript could go unread depending on which shape a
    given Codex version happens to produce."""
    raw = (
        '{"type":"response_item","payload":{"type":"custom_tool_call","call_id":"call_x","name":"exec","input":"echo hi"}}\n'
        '{"type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"call_x",'
        '"output":"Script completed\\nWall time 0.1 seconds\\nOutput:\\n{\\"chunk_id\\":\\"z\\",\\"exit_code\\":0,\\"output\\":\\"hi\\\\n\\"}"}}\n'
    )
    events = ta.parse_codex_transcript(raw)
    tool_use = next(e for e in events if e.get("type") == "tool_use")
    assert tool_use["error"] is False


def test_codex_a_non_exec_tool_call_is_never_treated_as_confirmed() -> None:
    """No success/failure convention has been observed for a non-`exec`
    (e.g. MCP) tool call on this host at all - undeterminable is refused,
    never assumed successful, the same rule `skillc/credential.py` applies
    to an unparseable expiry."""
    raw = (
        '{"type":"response_item","payload":{"type":"custom_tool_call","call_id":"call_y","name":"some_mcp_tool","input":"{}"}}\n'
        '{"type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"call_y",'
        '"output":[{"type":"input_text","text":"looks fine"}]}}\n'
    )
    events = ta.parse_codex_transcript(raw)
    tool_use = next(e for e in events if e.get("type") == "tool_use")
    assert tool_use["error"] is True


def test_codex_an_unparseable_exit_code_is_never_assumed_zero() -> None:
    raw = (
        '{"type":"response_item","payload":{"type":"custom_tool_call","call_id":"call_z","name":"exec","input":"echo hi"}}\n'
        '{"type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"call_z",'
        '"output":[{"type":"input_text","text":"no json chunk in here at all"}]}}\n'
    )
    events = ta.parse_codex_transcript(raw)
    tool_use = next(e for e in events if e.get("type") == "tool_use")
    assert tool_use["error"] is True


def test_codex_skill_heuristic_is_never_fooled_by_an_unrelated_path() -> None:
    """The skill heuristic matches a `skills/<name>/SKILL.md` path
    specifically - an unrelated file read must never be misread as a
    skill invocation."""
    raw = (
        '{"type":"response_item","payload":{"type":"custom_tool_call","call_id":"call_w","name":"exec","input":"cat README.md"}}\n'
        '{"type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"call_w",'
        '"output":[{"type":"input_text","text":"{\\"chunk_id\\":\\"q\\",\\"exit_code\\":0,\\"output\\":\\"hello\\"}"}]}}\n'
    )
    events = ta.parse_codex_transcript(raw)
    assert not any(e.get("type") == "skill_invocation" for e in events)


# ---------------------------------------------------------- malformed input

@pytest.mark.parametrize("parse", [ta.parse_claude_code_transcript, ta.parse_codex_transcript])
def test_a_malformed_line_is_skipped_not_fatal(parse) -> None:
    raw = "not json at all\n{}\n"
    assert parse(raw) == []


# ------------------------------------------------ cross-model review findings

def test_claude_code_a_first_prompt_delivered_as_a_text_block_is_read() -> None:
    """Cross-model review: an earlier version only read `content` as a
    plain string, so a real prompt delivered as `[{"type": "text", ...}]`
    (a shape the Messages API allows) silently vanished."""
    raw = (
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"the real prompt"}]}}\n'
    )
    events = ta.parse_claude_code_transcript(raw)
    verify_first_user_message(events, "the real prompt")  # must not raise


def test_claude_code_a_text_block_prompt_is_not_shadowed_by_a_later_string_message() -> None:
    """Red case for the same finding: without the fix, the text-block
    prompt above is invisible, and `verify_first_user_message` would
    instead accept a LATER string-valued user message as if it were the
    first one - which must never happen once the real first prompt is a
    text block."""
    raw = (
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"the real prompt"}]}}\n'
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n'
        '{"type":"user","message":{"role":"user","content":"a later, different message"}}\n'
    )
    events = ta.parse_claude_code_transcript(raw)
    with pytest.raises(PromptDeliveryError):
        verify_first_user_message(events, "a later, different message")


def test_claude_code_a_tool_result_only_turn_still_never_becomes_a_message() -> None:
    raw = (
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Bash","input":{}}]}}\n'
        '{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","content":"ok","is_error":false}]}}\n'
    )
    events = ta.parse_claude_code_transcript(raw)
    assert not any(e.get("role") == "user" for e in events)


def test_codex_exit_code_mixed_chunks_any_failure_anywhere_wins() -> None:
    """Cross-model review: an earlier version returned the FIRST chunk's
    exit code found, so a successful chunk ahead of a failed one certified
    the failed one's output as confirmed. The worst (any non-zero) must
    win regardless of order."""
    raw = (
        '{"type":"response_item","payload":{"type":"custom_tool_call","call_id":"call_m","name":"exec","input":"echo hi"}}\n'
        '{"type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"call_m",'
        '"output":[{"type":"input_text","text":"{\\"chunk_id\\":\\"a\\",\\"exit_code\\":0,\\"output\\":\\"unrelated\\"}\\n'
        '{\\"chunk_id\\":\\"b\\",\\"exit_code\\":1,\\"output\\":\\"touched:cccc3333dddd4444\\"}"}]}}\n'
    )
    events = ta.parse_codex_transcript(raw)
    tool_use = next(e for e in events if e.get("type") == "tool_use")
    assert tool_use["error"] is True


def test_codex_skill_heuristic_requires_a_real_skills_directory_boundary() -> None:
    """Cross-model review: the unanchored regex matched a directory merely
    ENDING in the letters 'skills' (`oldskills`), which is not a `skills/`
    directory at all."""
    raw = (
        '{"type":"response_item","payload":{"type":"custom_tool_call","call_id":"call_o","name":"exec",'
        '"input":"cat /work/oldskills/demo-skill/SKILL.md"}}\n'
        '{"type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"call_o",'
        '"output":[{"type":"input_text","text":"{\\"chunk_id\\":\\"c\\",\\"exit_code\\":0,\\"output\\":\\"hi\\"}"}]}}\n'
    )
    events = ta.parse_codex_transcript(raw)
    assert not any(e.get("type") == "skill_invocation" for e in events)


def test_codex_skill_heuristic_requires_a_real_skill_md_filename_boundary() -> None:
    """Cross-model review: the unanchored regex also matched a suffixed
    backup file (`SKILL.md.bak`), never a real invocation."""
    raw = (
        '{"type":"response_item","payload":{"type":"custom_tool_call","call_id":"call_p","name":"exec",'
        '"input":"cat /work/skills/demo-skill/SKILL.md.bak"}}\n'
        '{"type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"call_p",'
        '"output":[{"type":"input_text","text":"{\\"chunk_id\\":\\"d\\",\\"exit_code\\":0,\\"output\\":\\"hi\\"}"}]}}\n'
    )
    events = ta.parse_codex_transcript(raw)
    assert not any(e.get("type") == "skill_invocation" for e in events)


# ------------------------------------------------ codex run metadata (#12)


def test_codex_run_metadata_reads_the_last_turn_and_the_last_token_count() -> None:
    raw = (FIXTURES / "codex" / "run-metadata.jsonl").read_text(encoding="utf-8")
    meta = ta.codex_run_metadata(raw)
    assert meta["model"] == "fake-model-b"  # the LAST turn_context, not the first
    assert meta["reasoning_effort"] == "high"
    assert meta["cli_version"] == "9.9.9"
    assert meta["token_usage"] == {
        "input_tokens": 300, "cached_input_tokens": 120, "output_tokens": 30,
        "reasoning_output_tokens": 6, "total_tokens": 330,
    }
    assert meta["final_agent_message"] == "Done: the helper now passes every example."


def test_codex_run_metadata_never_copies_account_identifiers() -> None:
    raw = (FIXTURES / "codex" / "run-metadata.jsonl").read_text(encoding="utf-8")
    assert "user-FAKE" not in json.dumps(ta.codex_run_metadata(raw))


def test_codex_run_metadata_reports_absent_as_none_never_a_default() -> None:
    """Red case: a rollout with no identity events (the existing no-op
    fixture) must yield None everywhere, never a guessed model."""
    raw = (FIXTURES / "codex" / "no-op.jsonl").read_text(encoding="utf-8")
    meta = ta.codex_run_metadata(raw)
    assert meta["model"] is None
    assert meta["cli_version"] is None
    assert meta["token_usage"] is None
# ------------------------------------------- Claude Code skill listing (#124)


def _listing_line(names: object, *, initial: bool = True) -> str:
    return json.dumps({"type": "attachment", "attachment": {
        "type": "skill_listing", "names": names, "skillCount": 0, "isInitial": initial, "content": "",
    }})


def test_claude_skill_listing_reads_every_listed_name_in_order() -> None:
    raw = "\n".join([
        _listing_line(["tdd", "diagnosing-bugs"]),
        json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}),
        _listing_line(["diagnosing-bugs", "late-skill"], initial=False),
    ])
    assert ta.claude_code_skill_listing(raw) == ("tdd", "diagnosing-bugs", "late-skill")


def test_claude_skill_listing_absent_is_none_not_empty() -> None:
    """The distinction the discovery check stands on: no attachment means
    NOT OBSERVABLE (UNMEASURED downstream), never "the client listed
    nothing", which would turn every installed skill into a false
    not-listed."""
    raw = json.dumps({"type": "user", "message": {"role": "user", "content": "skill_listing mentioned in prose"}})
    assert ta.claude_code_skill_listing(raw) is None
    # The control: a real attachment with an empty list IS an observation.
    assert ta.claude_code_skill_listing(_listing_line([])) == ()


def test_claude_skill_listing_unreadable_attachment_is_none_not_an_absence() -> None:
    """Counter-model review (#124): a listing the parser cannot fully read is
    an incomplete population - never a basis for `not-listed`."""
    assert ta.claude_code_skill_listing(_listing_line("tdd")) is None
    assert ta.claude_code_skill_listing(_listing_line(["tdd", 7])) is None
    assert ta.claude_code_skill_listing(_listing_line([{"name": "tdd"}])) is None
    # A valid initial listing followed by an unreadable delta: still None.
    raw = "\n".join([_listing_line(["tdd"]), _listing_line([{"name": "x"}], initial=False)])
    assert ta.claude_code_skill_listing(raw) is None
    # The control: the same shapes, readable, are an observation.
    raw_ok = "\n".join([_listing_line(["tdd"]), _listing_line(["x"], initial=False)])
    assert ta.claude_code_skill_listing(raw_ok) == ("tdd", "x")


def test_claude_skill_listing_does_not_disturb_the_event_stream() -> None:
    """The attachment line is not a message: `verify_first_user_message`
    must still see the real prompt first."""
    raw = "\n".join([
        _listing_line(["tdd"]),
        json.dumps({"type": "user", "message": {"role": "user", "content": "the prompt"}}),
    ])
    assert ta.parse_claude_code_transcript(raw) == [{"role": "user", "content": "the prompt"}]


def test_claude_skill_listing_delta_only_is_none_not_a_complete_listing() -> None:
    """Counter-model review (#124): a delta names additions, not the full set.
    Without a readable initial listing, an omission cannot be inferred."""
    assert ta.claude_code_skill_listing(_listing_line(["late-skill"], initial=False)) is None
    # The control: the same delta after an initial listing is merged in.
    raw = "\n".join([_listing_line(["tdd"]), _listing_line(["late-skill"], initial=False)])
    assert ta.claude_code_skill_listing(raw) == ("tdd", "late-skill")
