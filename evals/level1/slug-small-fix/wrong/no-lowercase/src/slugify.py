"""Plausible wrong fix: a rewrite that forgot to lowercase first."""

import re


def slugify(title):
    """Collapse runs of non-alphanumerics to one hyphen, trim hyphens."""
    out = re.sub(r"[^A-Za-z0-9]+", "-", title)
    return out.strip("-")
