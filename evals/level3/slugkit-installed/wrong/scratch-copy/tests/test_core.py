"""Rewritten by the candidate to test the scratch fix (known-bad (a)) -
`slugkit/core.py`, what actually ships, is never exercised here."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scratch.core import slugify


def test_trailing_hyphen():
    assert slugify("Hello, World!") == "hello-world"
