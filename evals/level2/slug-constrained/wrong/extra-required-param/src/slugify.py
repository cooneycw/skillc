"""Turn a title into a URL slug - but requires a second, undeclared argument."""

import re


def slugify(title, strict):
    """Lowercase, collapse runs of non-alphanumerics to one hyphen, trim hyphens.

    `strict` has no default: every call site that used the original one-argument
    interface now raises TypeError, which is exactly the interface-stability
    violation this candidate exists to be caught by.
    """
    out = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return out.strip("-")
