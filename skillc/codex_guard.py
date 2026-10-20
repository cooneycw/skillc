"""The controller's record of the nested-codex guard (#434 PR 2b, D3).

`docker/fixture-service/skillc-codex-guard.py` runs inside the attempt, AS the
candidate, in front of every bare `codex`. It sends each decision here over the
attempt's one trigger socket as one `codex_guard` request, and this session
keeps it. The record lives in the controller, so nothing in the container can
edit it (orchestrator ruling on D3 condition 4: a file the guard could append
to, the subject could edit too).

COUNTS, AND WHEN THEY MEAN SOMETHING (orchestrator ruling):

- `confirmed`: `refused-nested` decisions, where the guard found a codex
  ancestor.
- `ancestry_unknown`: `refused-ancestry-unknown`, a call the guard could not
  place, refused rather than passed.
- `suspected`: top-level launches beyond the EXPECTED count. The harness
  launches the agent once, plus once per controller turn it delivers (#279:
  each approval is a fresh top-level `codex exec ... resume`), so it expects
  `controller_turns.expected_top_level(delivered)` launches. Any more is a
  codex started with no codex ancestor, which is what a double-fork reparent
  to PID 1 looks like. It is reported as suspected, not confirmed.
- `status`:
  - `zero` only with a healthy channel AND exactly the expected number of
    `passed-top-level` AND nothing refused. FEWER than expected is `unknown`:
    a delivered turn the guard never saw did not come through it;
  - `observed` when any of the three counts is above zero;
  - `unknown` otherwise: an unhealthy channel, or no top-level launch recorded
    at all, which means the guard's send failed or the guard never ran.

WHAT ZERO DOES NOT SAY. A codex called by absolute path (the real codex.js
or native binary) never runs the guard, so it sends nothing, and the count
can read `zero` with it having happened. `zero` means no nested launch came
through the guard. The attempt's composed decide also marks this record
unhealthy when it refuses a guard request before it reaches `decide` here
(`FixtureSession.watch`).

A subject can send `refused-nested` lines against itself. That only hurts the
subject, so they are counted as reported.

The request is closed: exactly `{op, decision, argv_digest}`, a decision from
the fixed set, and a sha256 digest. Anything else is refused, and so is a
request after finalization or beyond `MAX_DECISIONS`. Every refusal marks the
record's channel unavailable, so a malformed or flooding sender can only push
the count to `unknown`.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .decide_reply_channel import ChannelRefusal

DECISIONS = ("passed-top-level", "refused-nested", "refused-ancestry-unknown")
REQUEST_KEYS = frozenset({"op", "decision", "argv_digest"})
MAX_DECISIONS = 1000
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass
class CodexGuardSession:
    """One attempt's guard record, decided and recorded before each reply."""

    attempt_id: str
    decisions: list[dict[str, Any]] = field(default_factory=list)
    channel_unavailable: bool = False
    finalized: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def decide(self, request: Mapping[str, object]) -> Mapping[str, object]:
        with self._lock:
            problem = self._problem(request)
            if problem is not None:
                self.channel_unavailable = True
                raise ChannelRefusal(f"codex_guard: {problem}")
            self.decisions.append({"seq": len(self.decisions) + 1, "decision": request["decision"],
                                   "argv_digest": request["argv_digest"]})
            return {"recorded": len(self.decisions)}

    def _problem(self, request: Mapping[str, object]) -> str | None:
        if self.finalized:
            return "the record is finalized"
        if set(request) != REQUEST_KEYS or request.get("op") != "codex_guard":
            return f"fields must be exactly {sorted(REQUEST_KEYS)}"
        if request.get("decision") not in DECISIONS:
            return f"unknown decision {request.get('decision')!r}"
        digest = request.get("argv_digest")
        if not isinstance(digest, str) or not _DIGEST.match(digest):
            return "argv_digest is not a sha256 digest"
        if len(self.decisions) >= MAX_DECISIONS:
            return f"more than {MAX_DECISIONS} decisions"
        return None

    def finalize(self) -> dict[str, Any]:
        """The record, once; later requests are refused."""
        with self._lock:
            self.finalized = True
            return summarize(self.attempt_id, list(self.decisions), self.channel_unavailable)


def summarize(attempt_id: str, decisions: list[dict[str, Any]], channel_unavailable: bool,
              expected_top_level: int = 1, *, nested_policy: str | None = None) -> dict[str, Any]:
    top = sum(1 for d in decisions if d["decision"] == "passed-top-level")
    confirmed = sum(1 for d in decisions if d["decision"] == "refused-nested")
    ancestry_unknown = sum(1 for d in decisions if d["decision"] == "refused-ancestry-unknown")
    suspected = max(0, top - expected_top_level)
    if confirmed or ancestry_unknown or suspected:
        status = "observed"
    elif channel_unavailable or top != expected_top_level:
        status = "unknown"
    else:
        status = "zero"
    nested: dict[str, Any] = {"status": status, "top_level": top, "confirmed": confirmed, "suspected": suspected,
                              "ancestry_unknown": ancestry_unknown}
    if expected_top_level != 1:
        # Only a multi-turn attempt (#279) records it, so a single-turn
        # attempt's stored record is byte-identical to before.
        nested["expected_top_level"] = expected_top_level
    if nested_policy is not None:
        # Only an attempt under a declared nested-codex policy (#279) records
        # the channel's health beside the counts, so `refusals_only` can see it
        # wherever only `nested` travels; every other record is unchanged.
        nested["nested_policy"] = nested_policy
        nested["channel_unavailable"] = channel_unavailable
    return {
        "kind": "codex-guard", "attempt_id": attempt_id, "decisions": decisions,
        "channel_unavailable": channel_unavailable, "nested": nested,
    }


#: #279 (orchestrator ruling G1): what a declaration may declare about nested
#: codex. `refusal-expected`: flow:auto's Step 6 improvises its counter-model
#: review as a nested codex (CPP 86641e8 ships no review skill), and the guard
#: REFUSING it (exit 3, before any model contact) is containment working.
#: Absent, every refusal stops and blocks credit, exactly as before.
NESTED_POLICIES = ("refusal-expected",)


def refusals_only(nested: Mapping[str, Any] | None) -> bool:
    """True only when every nested launch the guard saw was REFUSED: at least
    one confirmed refusal, none suspected (a top-level launch beyond the
    expected count - a nested launch that was passed through), none of unknown
    ancestry, exactly the expected top-level launches, and a channel the
    record says was healthy (`channel_unavailable` False, which only an
    opted-in attempt records). Anything else is not a refusal-only record."""
    if not isinstance(nested, Mapping) or nested.get("status") != "observed" \
            or nested.get("channel_unavailable") is not False:
        return False
    expected = nested.get("expected_top_level", 1)
    return (isinstance(nested.get("confirmed"), int) and nested["confirmed"] > 0
            and nested.get("suspected") == 0 and nested.get("ancestry_unknown") == 0
            and nested.get("top_level") == expected)


def credit_block(record: Mapping[str, Any] | None, *, nested_policy: str | None = None) -> str | None:
    """The credit gate's reason, or `None` when the attempt may be credited
    (orchestrator ruling: enforced where #442 enforces a server-side tool, never
    in the frozen judge). A missing record is unknown, never zero. Under the
    declared `refusal-expected` policy (#279) a refusals-only record is
    credited; a channel the guard could not trust still is not."""
    if nested_policy is not None and nested_policy not in NESTED_POLICIES:
        return f"not credited: unknown nested-codex policy {nested_policy!r}"
    nested = record.get("nested") if isinstance(record, Mapping) else None
    if not isinstance(nested, Mapping) or nested.get("status") not in ("zero", "observed", "unknown"):
        return "not credited: nested-codex count unknown (no guard record)"
    if nested_policy == "refusal-expected" and refusals_only(nested):
        return None
    if nested["status"] == "observed":
        return (f"not credited: nested codex observed (confirmed={nested.get('confirmed')}, "
                f"suspected={nested.get('suspected')}, ancestry-unknown={nested.get('ancestry_unknown')})")
    if nested["status"] == "unknown":
        return "not credited: nested-codex count unknown"
    return None
