"""Plausible wrong fix: trims the ends but leaves spaces inside the slug."""

import re


def slugify(title):
    """Lowercase, hyphenate punctuation, trim spaces and hyphens."""
    out = re.sub(r"[^a-z0-9 ]+", "-", title.lower())
    return out.strip(" -")
