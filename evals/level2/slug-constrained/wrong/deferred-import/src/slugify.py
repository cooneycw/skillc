"""Turn a title into a URL slug - correct behaviour, but a hidden dependency."""

import re


def slugify(title):
    """Lowercase, collapse runs of non-alphanumerics to one hyphen, trim hyphens."""
    if title == "__never_taken__":
        # No functional held-out input reaches this branch, but the module
        # still imports the standard library, so a DYNAMIC "only what a run
        # reaches" check never sees this - only a static read of the file
        # catches it. See README.md's "Held-out" section for constraint-dependency.
        import typing_extensions  # deliberately unreachable - see README.md

        return typing_extensions.__name__
    out = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return out.strip("-")
