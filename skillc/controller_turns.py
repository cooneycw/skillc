"""Controller-delivered turns (#279 PR 1): the approval a live flow:auto
attempt needs to pass Step 3.

CPP's flow:auto pauses at Step 3 for a reviewer's approval of its plan, and
the gate has no bypass. An unattended attempt therefore stops there with a
plan (#434's acceptance revision). To reach Step 6, the CONTROLLER sends a
second user turn into the same client session, after the first turn ends.

WHAT IS DECLARED. Turns are per CASE, never "always after a clean exit"
(orchestrator ruling). Delivering an approval after a CLEAN case's "No longer
needed" would push the agent toward implementing and contaminate the
necessity measure, so a case declared with no turns never receives one. The
schema is closed and version 1:

    {"version": 1, "by_case": {"<case>": [{"text": "<literal>"}, ...], ...}}

- the case keys must equal the declaring caller's cases exactly;
- each case has 0 to `MAX_TURNS` turns;
- a text is a non-empty literal: no templating, nothing filled in at run time.

A caller binds the whole object into its declaration digest (#434's
`task.turns`), so an edited text needs a fresh approval.

THE CONTROLLER NEVER INTERPRETS THE AGENT'S TEXT. A turn is delivered when the
previous turn EXITED with code 0 and the case declares another one. A turn
that timed out, was cancelled or exited non-zero ends the attempt. Whether a
plan existed before the approval is graded afterwards from the record, not
decided here.

THE RESUME ARGV, MEASURED on the pinned client (codex-cli 0.157.1, offline, in
the never-rebuilt #375 image, 2026-10-18):
- `codex exec [EXEC FLAGS] resume <SESSION_ID> <PROMPT>` is accepted. Exec's
  flags placed BEFORE `resume` take effect, `--sandbox` included, and the
  header shows the same session id and sandbox mode.
- `--sandbox` placed AFTER `resume` is refused (`unexpected argument
  '--sandbox'`), because the `resume` subcommand has no such flag.
- The resumed run appends to the SAME rollout file, so one transcript covers
  every turn.
So the resume argv is the turn-1 argv minus its prompt, then `resume`, the
session id and the text: `[*base_argv, "resume", <id>, <text>]`. Deriving it
from `base_argv`, not a hard-coded `codex`, lets a scripted actor that
understands `resume` rehearse a multi-turn run with no model (#434's
`--rehearse actor`).

THE SESSION ID IS CONTROLLER-HELD. It is read from turn 1's own stderr, which
the backend captures from the exec stream, never from the rollout file the
agent could edit. The pinned client prints a header there before it does
anything else:

    OpenAI Codex v0.157.1
    --------
    ...
    session id: 01a14f6a-cd7e-7851-8061-5cdeaaca5863
    --------

Only that header block is read (from the version line to the second
separator), it must be the INITIAL output (only the client's own start-up
warnings may precede it), and it must hold exactly one `session id:` line with
a UUID. Text the agent prints later cannot supply or replace it, not even a
complete forged header when the real one is missing. No header, or an
ambiguous one, means no further turn.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

SCHEMA_VERSION = 1
MAX_TURNS = 3
MAX_TEXT_CHARS = 4000
CLIENTS = ("codex",)
RESUME = "resume"

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HEADER_START = re.compile(r"^OpenAI Codex v\S+\s*$")
_SEPARATOR = re.compile(r"^-{4,}\s*$")
_SESSION_LINE = re.compile(r"^session id:\s*(\S+)\s*$")
#: What the pinned client prints before its header (measured): PATH-alias
#: warnings and the stdin notice. Anything else before the header refuses it.
_STARTUP = re.compile(r"^(WARNING: .*|Reading additional input from stdin\.\.\.|\s*)$")


class TurnsRefused(ValueError):
    """A turns declaration, or a request to build a turn, that is refused."""


@dataclass(frozen=True)
class Turns:
    """One case's controller turns, in delivery order."""

    texts: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.texts)


NO_TURNS = Turns()


@dataclass(frozen=True)
class CaseTurns:
    """The declared turns of every case."""

    by_case: Mapping[str, Turns]

    def for_case(self, case: str) -> Turns:
        if case not in self.by_case:
            raise TurnsRefused(f"no turns declared for case {case!r}: the declaration must name every case")
        return self.by_case[case]


def parse_turns(data: object, cases: Sequence[str]) -> CaseTurns:
    """Validate a v1 turns object against the declaring caller's `cases`."""
    if not isinstance(data, Mapping) or set(data) != {"version", "by_case"}:
        raise TurnsRefused("turns must be exactly {version, by_case}")
    if data["version"] != SCHEMA_VERSION or isinstance(data["version"], bool):
        raise TurnsRefused(f"turns version must be {SCHEMA_VERSION}")
    by_case = data["by_case"]
    if not isinstance(by_case, Mapping):
        raise TurnsRefused("turns.by_case must be an object keyed by case")
    if set(by_case) != set(cases):
        raise TurnsRefused(f"turns.by_case must name exactly the declared cases {sorted(cases)}, "
                           f"got {sorted(str(k) for k in by_case)}")
    parsed: dict[str, Turns] = {}
    for case in cases:
        entries = by_case[case]
        if not isinstance(entries, list) or len(entries) > MAX_TURNS:
            raise TurnsRefused(f"turns for case {case!r} must be a list of at most {MAX_TURNS}")
        texts = []
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, Mapping) or set(entry) != {"text"}:
                raise TurnsRefused(f"case {case!r} turn {index} must be exactly {{text}}")
            text = entry["text"]
            if not isinstance(text, str) or not text.strip():
                raise TurnsRefused(f"case {case!r} turn {index}: text must be a non-empty string")
            if len(text) > MAX_TEXT_CHARS or "\x00" in text:
                raise TurnsRefused(f"case {case!r} turn {index}: text is over {MAX_TEXT_CHARS} chars or holds NUL")
            texts.append(text)
        parsed[case] = Turns(tuple(texts))
    return CaseTurns(parsed)


def session_id_from_header(stderr: bytes | None) -> str | None:
    """Turn 1's session id from the client's own header block, or `None`."""
    if not stderr:
        return None
    lines = stderr.decode("utf-8", errors="replace").splitlines()
    start = next((i for i, line in enumerate(lines) if _HEADER_START.match(line)), None)
    if start is None:
        return None
    # The header must be the INITIAL region: everything before it must be one
    # of the client's own start-up diagnostics. A header found later, after any
    # other output, could be the agent's (#279 counter-model review).
    if not all(_STARTUP.match(line) for line in lines[:start]):
        return None
    separators = [i for i in range(start + 1, len(lines)) if _SEPARATOR.match(lines[i])]
    if len(separators) < 2:
        return None
    found = [m.group(1) for line in lines[separators[0] + 1:separators[1]]
             if (m := _SESSION_LINE.match(line))]
    if len(found) != 1 or not _UUID.match(found[0]):
        return None
    return found[0]


def resume_argv(client: str, base_argv: Sequence[str], session_id: str, text: str) -> tuple[str, ...]:
    """The measured resume shape: `[*base_argv, "resume", <id>, <text>]`."""
    if client not in CLIENTS:
        raise TurnsRefused(f"controller turns support {list(CLIENTS)} only, not {client!r}")
    if not _UUID.match(session_id):
        raise TurnsRefused(f"not a session id: {session_id!r}")
    if RESUME in base_argv:
        raise TurnsRefused("base_argv already holds 'resume': the turn-1 argv must be a fresh exec")
    return (*base_argv, RESUME, session_id, text)


def expected_top_level(delivered: int) -> int:
    """Top-level client launches an attempt legitimately makes: the first turn
    plus one per delivered controller turn (orchestrator ruling, #434's guard)."""
    return 1 + delivered
