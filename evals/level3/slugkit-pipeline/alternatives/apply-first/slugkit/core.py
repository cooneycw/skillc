"""Core slug logic - an independently-shaped correct fix (character loop
instead of a regex substitution), to prove the installed path is checked by
behaviour, not source shape."""

import json
from importlib import resources


def _load_replacements():
    data = resources.files("slugkit.data").joinpath("replacements.json").read_text(encoding="utf-8")
    return json.loads(data)


def slugify(title):
    replacements = _load_replacements()
    text = title
    for symbol, word in replacements.items():
        text = text.replace(symbol, f" {word} ")
    out_chars = []
    prev_was_sep = False
    for ch in text.lower():
        if ("a" <= ch <= "z") or ("0" <= ch <= "9"):
            out_chars.append(ch)
            prev_was_sep = False
        elif not prev_was_sep:
            out_chars.append("-")
            prev_was_sep = True
    return "".join(out_chars).strip("-")
