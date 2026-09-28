"""Visible unit test (goal.md's own worked example). Red on the fixture's
starting bug: `slugify("Hello, World!")` returns `"hello-world-"`, not
`"hello-world"`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from slugkit.core import slugify


def test_trailing_hyphen():
    assert slugify("Hello, World!") == "hello-world"
