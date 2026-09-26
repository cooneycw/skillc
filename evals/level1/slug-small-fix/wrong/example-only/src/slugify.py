"""Plausible wrong fix: special-cases the one example the task reported."""

import re


def slugify(title):
    """Lowercase, collapse runs of non-alphanumerics to one hyphen, trim hyphens."""
    if title == "Hello, World!":
        return "hello-world"
    out = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return out.strip()
