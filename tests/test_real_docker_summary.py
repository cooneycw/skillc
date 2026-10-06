"""Tests for `ci/real_docker_summary.py` (#315): the leak-safe summary
formatter. The central claim is the positive-control test below - a planted
fake home-directory path and private IP, inside content this formatter is
handed, must never reach its output."""

from __future__ import annotations

from ci import check_real_docker_ran as c
from ci import real_docker_summary as s

SHA = "a" * 40
RUNNER_SHA = "b" * 40


def test_success_description_and_comment() -> None:
    result = c.Verdict(status=c.SUCCESS, reason="irrelevant - never read", executed_by_file={"tests.x": 1})
    desc = s.format_status_description(result, sha=SHA, runner_sha=RUNNER_SHA)
    assert desc.startswith("SUCCESS:")
    assert SHA[:12] in desc
    body = s.format_comment_body(result, sha=SHA, runner_sha=RUNNER_SHA)
    assert "SUCCESS" in body
    assert "tests.x" in body


def test_formatter_never_reads_verdict_reason() -> None:
    """Decoupling claim, made concrete: a `Verdict.reason` field planted
    with a fake home path and IP - simulating a future change to
    `check_real_docker_ran.py` that accidentally quotes raw failure content
    into `reason` - must not reach either posted string, because this
    formatter's sentences never include `reason` at all."""
    planted = "found at /home/planted-user, host 10.20.30.40, see failure above"
    result = c.Verdict(status=c.FAILURE, reason=planted, executed_by_file={"tests.x": 1},
                        failed_ids=("tests.x::test_one",))
    desc = s.format_status_description(result, sha=SHA, runner_sha=RUNNER_SHA)
    body = s.format_comment_body(result, sha=SHA, runner_sha=RUNNER_SHA)
    assert "planted-user" not in desc
    assert "planted-user" not in body
    assert "10.20.30.40" not in desc
    assert "10.20.30.40" not in body


def test_a_planted_path_and_ip_inside_a_failed_test_id_is_dropped() -> None:
    """Positive control: a `failed_ids` entry adversarially crafted to
    smuggle a path/IP through what is otherwise a trusted-looking field
    (pytest test ids are not supposed to contain these, but this proves the
    filter catches it if one somehow did, rather than assuming the input is
    already clean)."""
    poisoned_id = "tests.test_x::test_at_/home/planted-user_10.20.30.40"
    clean_id = "tests.test_x::test_ok"
    result = c.Verdict(status=c.FAILURE, reason="irrelevant", executed_by_file={"tests.test_x": 2},
                        failed_ids=(poisoned_id, clean_id))
    body = s.format_comment_body(result, sha=SHA, runner_sha=RUNNER_SHA)
    assert "planted-user" not in body
    assert "10.20.30.40" not in body
    assert clean_id in body
    assert "omitted" in body


def test_red_case_an_unfiltered_formatter_would_leak_the_planted_id() -> None:
    """Mutation check: a formatter that interpolates `failed_ids` directly,
    with no charset filter, WOULD leak the poisoned id - proving the test
    above actually exercises the filter rather than passing by accident."""
    poisoned_id = "tests.test_x::test_at_/home/planted-user_10.20.30.40"

    def unfiltered_body(ids: tuple[str, ...]) -> str:
        return "\n".join(f"- `{i}`" for i in ids)

    naive = unfiltered_body((poisoned_id,))
    assert "planted-user" in naive, "the unfiltered mutation does not leak - this red case is inert"
