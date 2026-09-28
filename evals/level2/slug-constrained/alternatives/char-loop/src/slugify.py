"""Turn a title into a URL slug, character by character (an alternative shape)."""


def slugify(title):
    """Lowercase, collapse runs of non-alphanumerics to one hyphen, trim hyphens."""
    out_chars = []
    prev_was_sep = False
    for ch in title.lower():
        if ("a" <= ch <= "z") or ("0" <= ch <= "9"):
            out_chars.append(ch)
            prev_was_sep = False
        elif not prev_was_sep:
            out_chars.append("-")
            prev_was_sep = True
    return "".join(out_chars).strip("-")
