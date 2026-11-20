"""The committed six-field wake capture is genuinely the ORIGINAL shape.

Imports only names the pre-B8a module already had (parse_context,
parse_reference, verify), so this PASSES on the parent commit, proving the
fixture is truly old-shape, and on every later commit, proving those
captures still verify."""

from __future__ import annotations

import json
from pathlib import Path

from skillc import wave_wake_capture as wc

CONTROL = Path(__file__).resolve().parent.parent / "controls" / "wave-wake-origin"


def test_the_committed_capture_verifies_with_the_original_api() -> None:
    binding = json.loads((CONTROL / "binding.json").read_text())
    assert set(binding["context"]) == {"attempt_id", "approved_declaration_digest",
                                       "policy_digest", "roles", "deadline_digest", "clock"}
    context = wc.parse_context(binding["context"])
    reference = wc.parse_reference(binding["reference"])
    assert context.digest == reference.context_digest
    result = wc.verify(CONTROL / "capture", reference, context)
    assert result["status"] == "CAPTURED" and result["outcome"] == "UNKNOWN"
    assert result["poke_count"] == 0 and result["complete"] is False
    assert [row["role"] for row in result["poke_counts"]] == ["worker-a", "worker-b"]
    assert all(row["pokes"] is None for row in result["poke_counts"])
