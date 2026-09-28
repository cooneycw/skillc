"""Known-bad (a): the trailing-hyphen fix, applied only to a SCRATCH copy -
`slugkit/core.py` itself, the declared package `pyproject.toml` actually
ships, is left with the original bug. `tests/test_core.py` was rewritten to
test THIS file instead, so the unit test passes while the installed path
still runs the buggy `slugkit/core.py`."""

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
