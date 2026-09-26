"""Valid alternative: find the alphanumeric runs and join them."""

import re


def slugify(title: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", title.lower()))
