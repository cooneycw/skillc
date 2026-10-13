"""The offline cache-miss oracle is checked against uv's REAL output (#360).

The live closure-preflight test once required the phrase "network is
disabled", which uv 0.9.7 never prints (it says "Network connectivity is
disabled", wrapped across lines). Its offline twins fed the oracle the same
invented phrase, so both agreed with each other and neither with uv; the
live test then failed on every real daemon while CI, which has no daemon,
stayed green. These cases pin the oracle to captured output instead.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE = _ROOT / "tests" / "fixtures" / "uv-offline-cache-miss-0.9.7.txt"


def _oracle():
    with patch.dict("os.environ", {"SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK": "none"}), \
            patch("shutil.which", return_value=None):
        ns = runpy.run_path(str(_ROOT / "tests" / "test_profile_closure_preflight_live.py"))
    return ns["_offline_cache_miss"]


def _real() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def test_real_uv_output_is_accepted() -> None:
    assert _oracle()(_real())


# uv wraps at a width, so a break can fall INSIDE either required phrase.
# The captured fixture happens to break between them, which alone would let a
# raw substring match pass; these cases are what make normalisation testable.
_WRAPPED_INSIDE = {
    "inside-network-clause": "Network connectivity is\n      disabled, but the requested data wasn't found in the cache for:",
    "inside-cache-clause": "Network connectivity is disabled, but the requested data wasn't found in\n      the cache for:",
}


@pytest.mark.parametrize("text", list(_WRAPPED_INSIDE.values()), ids=list(_WRAPPED_INSIDE))
def test_a_break_inside_either_phrase_is_accepted(text: str) -> None:
    assert _oracle()(text)


def test_an_unnormalised_oracle_rejects_the_wrapped_cases() -> None:
    # Mutation control for the case above: without whitespace normalisation the
    # same phrase check misses every wrapped-inside case.
    def raw(text: str) -> bool:
        return "Network connectivity is disabled" in text and "wasn't found in the cache" in text

    assert raw(_real())
    assert not any(raw(text) for text in _WRAPPED_INSIDE.values())


def test_the_old_oracle_rejects_real_uv_output() -> None:
    # Regression: the phrase pair this replaced never matches what uv says.
    text = _real()
    assert not ("wasn't found in the cache" in text and "network is disabled" in text)


@pytest.mark.parametrize("text", [
    "pydantic-core wasn't found in the cache and network is disabled",
    "requested data wasn't found in the cache for: pydantic-core",
    "Network connectivity is disabled",
    "error: failed to create directory .venv: Permission denied (os error 13)",
    "",
], ids=["invented-paraphrase", "cache-miss-only", "network-only", "permission-failure", "empty"])
def test_other_failures_are_rejected(text: str) -> None:
    assert not _oracle()(text)
