"""Plausible wrong fix: trims the trailing hyphen the report named, not the leading one."""

import re


def slugify(title):
    """Lowercase, collapse runs of non-alphanumerics to one hyphen, trim hyphens."""
    out = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return out.rstrip("-")
