"""Tests for `ci/real_docker_trigger.py` (#315, R3 + R4): trigger-comment
selection, dedup-by-id, and the owner-credential check."""

from __future__ import annotations

from ci import real_docker_trigger as t

OWNER = "cooneycw"
SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


def _comment(comment_id: int, login: str, body: str) -> dict[str, object]:
    return {"id": comment_id, "user": {"login": login}, "body": body}


def test_an_owner_comment_with_the_command_is_selected() -> None:
    comments = [_comment(1, OWNER, f"/run-real-docker {SHA}")]
    result = t.select_requested_shas(comments, owner_login=OWNER, processed_ids=frozenset())
    assert result.requests == ((1, SHA),)
    assert result.newly_seen_ids == (1,)


def test_a_non_owner_comment_with_the_command_is_ignored_not_merely_refused() -> None:
    """R4: the text alone proves nothing - only the API-reported login does."""
    comments = [_comment(2, "someone-else", f"/run-real-docker {SHA}")]
    result = t.select_requested_shas(comments, owner_login=OWNER, processed_ids=frozenset())
    assert result.requests == ()
    assert result.newly_seen_ids == (2,), "still marked seen, so it is never re-examined on a later edit"


def test_an_owner_comment_that_claims_to_be_someone_else_in_its_own_text_is_still_ignored() -> None:
    """Never trust the comment's own text about who is asking - only the
    API's user.login field, which the comment body cannot forge."""
    comments = [_comment(3, "someone-else", f"I am {OWNER}, really: /run-real-docker {SHA}")]
    result = t.select_requested_shas(comments, owner_login=OWNER, processed_ids=frozenset())
    assert result.requests == ()


def test_a_previously_processed_id_is_never_re_examined_even_if_edited() -> None:
    """R3's central claim: an edit to an old comment (same id, new body)
    must not re-trigger, because the id was already recorded as processed -
    regardless of what the edited body now says."""
    comments = [_comment(4, OWNER, f"/run-real-docker {SHA}")]
    result = t.select_requested_shas(comments, owner_login=OWNER, processed_ids=frozenset({4}))
    assert result.requests == ()
    assert result.newly_seen_ids == (), "already-processed ids are not re-added either"


def test_an_ordinary_comment_mentioning_the_phrase_mid_sentence_does_not_trigger() -> None:
    comments = [_comment(5, OWNER, f"I ran /run-real-docker {SHA} yesterday by hand, fyi")]
    result = t.select_requested_shas(comments, owner_login=OWNER, processed_ids=frozenset())
    assert result.requests == ()
    assert result.newly_seen_ids == (5,)


def test_a_too_short_hex_string_does_not_match() -> None:
    comments = [_comment(6, OWNER, "/run-real-docker abc123")]
    result = t.select_requested_shas(comments, owner_login=OWNER, processed_ids=frozenset())
    assert result.requests == ()


def test_multiple_comments_in_one_batch_are_each_handled_independently() -> None:
    comments = [
        _comment(10, OWNER, f"/run-real-docker {SHA}"),
        _comment(11, "someone-else", f"/run-real-docker {SHA}"),
        _comment(12, OWNER, "unrelated comment"),
    ]
    result = t.select_requested_shas(comments, owner_login=OWNER, processed_ids=frozenset())
    assert result.requests == ((10, SHA),)
    assert set(result.newly_seen_ids) == {10, 11, 12}


def test_red_case_deduping_by_acted_on_instead_of_by_seen_would_allow_an_edit_attack() -> None:
    """Mutation check: a version of this logic that only remembers ids it
    ACTED ON (i.e. only records ids that matched and were from the owner)
    would let a non-matching or non-owner comment be re-examined on a later
    poll after being edited - exactly the attack R3 exists to close. Proves
    the real implementation marks EVERY seen id, not only the triggered
    ones, by showing the two disagree on this case."""
    first_tick = [_comment(20, "someone-else", "innocuous comment, no command here")]
    first = t.select_requested_shas(first_tick, owner_login=OWNER, processed_ids=frozenset())
    assert not first.requests
    # The real implementation marks id 20 as seen even though nothing matched.
    assert 20 in first.newly_seen_ids

    # A "remembers only acted-on ids" mutation would NOT have recorded 20,
    # so on the next tick (after an edit adding the command, same id) it
    # would still be absent from processed_ids and would fire.
    acted_on_only: set[int] = set()
    for triggered_pair in first.requests:
        acted_on_only.add(triggered_pair[0])
    assert 20 not in acted_on_only, (
        "this demonstrates the mutation's state would still be empty here - "
        "the correct implementation's processed_ids (newly_seen_ids) is what must be persisted instead"
    )
