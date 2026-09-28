"""Core slug logic - correctly fixed. Known-bad (c) is entirely in cli.py:
the entry-point function was renamed without updating pyproject.toml's
`[project.scripts]` target."""

import json
import re
from importlib import resources


def _load_replacements():
    data = resources.files("slugkit.data").joinpath("replacements.json").read_text(encoding="utf-8")
    return json.loads(data)


def slugify(title):
    replacements = _load_replacements()
    text = title
    for symbol, word in replacements.items():
        text = text.replace(symbol, f" {word} ")
    out = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return out.strip("-")
