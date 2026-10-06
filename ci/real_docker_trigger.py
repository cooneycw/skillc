"""Trigger-comment selection for the `<agent-host>` real-Docker runner
(#315, R3 + R4). Pure decision logic over already-fetched GitHub API data;
the actual `gh api` calls and state-file I/O belong to the polling wrapper,
not here - this module only decides, given a batch of comments and the
state carried from the previous tick, which ones request a run and which
comment ids to remember as processed.

R3: `since=` filters on a comment's `updated_at`, so an EDITED old comment
is returned again by the API on a later poll. Fixing this by remembering
only "ids we have already ACTED on" is not enough: a comment that looked
like ordinary text on first sight and was edited afterward to add the
trigger command would then look new (never acted on) and fire on the edit -
exactly the attack this module exists to close. So a comment id is recorded
as processed, and its content is read, EXACTLY ONCE - the first time it is
seen - regardless of whether that first sight matched the command or not.
Every later sighting of the same id (an edit) is ignored outright, never
re-evaluated against its new body.

R4, restated precisely because it is easy to overstate: comparing a
comment's `user.login` to the repository's `owner.login` proves the
comment was posted through the OWNER'S CREDENTIAL, not that a human owner
personally decided to trigger this run. Fleet sessions acting for the
owner post through that same credential, and are an expected, accepted
source of trigger comments (the VM's isolation - ADR 0007 - is what makes
that acceptable, not an assumption that only the human types the command).
This module does not and cannot tell the two apart; it only answers "did
this come from the owner's account", which is the question it is scoped
to answer.

PURE: no network, no file I/O - `comments` is already-fetched API data
(list of dicts shaped like GitHub's issue-comments response), `owner_login`
is already resolved, `processed_ids` is already loaded from the state file
by the caller.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: `/run-real-docker <sha>` - EXACTLY 40 hex characters, never an
#: abbreviated sha (orchestrator review, B3): `run-real-docker` compares
#: the checkout's full `rev-parse HEAD` against the requested string
#: byte-for-byte, so a 7-40 character range let every abbreviated request
#: self-refuse as a checkout mismatch before ever running a test. Anchored
#: to the whole comment body after stripping surrounding whitespace - a
#: command embedded mid-sentence does not count, so an ordinary comment
#: that happens to mention the phrase cannot trigger anything by accident.
_COMMAND_RE = re.compile(r"^/run-real-docker\s+([0-9a-fA-F]{40})\s*$")


@dataclass(frozen=True)
class TriggerSelection:
    #: (comment_id, requested_sha) pairs to act on, in the order they were
    #: encountered in the input batch.
    requests: tuple[tuple[int, str], ...]
    #: Every comment id examined this tick (matched or not, owner or not) -
    #: the caller persists these into its processed-ids state so none of
    #: them is ever re-read, including after an edit.
    newly_seen_ids: tuple[int, ...]


def select_requested_shas(
    comments: list[dict[str, object]],
    *,
    owner_login: str,
    processed_ids: frozenset[int],
) -> TriggerSelection:
    requests: list[tuple[int, str]] = []
    newly_seen: list[int] = []

    for comment in comments:
        raw_id = comment.get("id")
        if not isinstance(raw_id, int) or raw_id in processed_ids:
            continue  # already processed (or malformed) - an edit never re-enters here
        newly_seen.append(raw_id)

        user = comment.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        if login != owner_login:
            continue  # not the owner's credential - ignored, not merely refused loudly

        body = comment.get("body")
        if not isinstance(body, str):
            continue
        match = _COMMAND_RE.match(body.strip())
        if match is None:
            continue
        requests.append((raw_id, match.group(1)))

    return TriggerSelection(requests=tuple(requests), newly_seen_ids=tuple(newly_seen))
