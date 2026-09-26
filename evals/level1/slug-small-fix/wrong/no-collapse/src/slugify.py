"""Plausible wrong fix: a rewrite that maps each separator to its own hyphen."""

import re


def slugify(title):
    """Lowercase, replace non-alphanumerics with hyphens, trim hyphens."""
    out = re.sub(r"[^a-z0-9]", "-", title.lower())
    return out.strip("-")
