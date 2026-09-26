"""Plausible wrong fix: correct behaviour, but the public name changed."""

import re


def make_slug(title):
    """Lowercase, collapse runs of non-alphanumerics to one hyphen, trim hyphens."""
    out = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return out.strip("-")
