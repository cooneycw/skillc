"""Core slug logic: apply symbol replacements, then lowercase and collapse.
Reference outcome for the slugkit-installed task."""

import json
import re
from importlib import resources


def _load_replacements():
    """The symbol->word table, read from the SHIPPED package data - never a
    hardcoded constant, so a future locale/translation swap needs no code
    change (goal.md's own stated reason)."""
    data = resources.files("slugkit.data").joinpath("replacements.json").read_text(encoding="utf-8")
    return json.loads(data)


def slugify(title):
    """Apply replacements, lowercase, collapse runs of non-alphanumerics to
    one hyphen, trim hyphens."""
    replacements = _load_replacements()
    text = title
    for symbol, word in replacements.items():
        text = text.replace(symbol, f" {word} ")
    out = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return out.strip("-")

# Housekeeping note: the replacements table is read at call time, by design.
