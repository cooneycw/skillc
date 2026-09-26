"""Plausible wrong fix: correct behaviour, but reaches outside the standard library.

`pytest` is installed in skillc's own dev environment, so without the grader's
site-packages isolation this candidate would pass every criterion.
"""

import re

import pytest  # noqa: F401 - the dependency R4 forbids


def slugify(title):
    """Lowercase, collapse runs of non-alphanumerics to one hyphen, trim hyphens."""
    out = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return out.strip("-")
