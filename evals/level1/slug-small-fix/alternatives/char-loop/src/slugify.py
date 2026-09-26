"""Valid alternative: a character loop, no regular expressions."""


def slugify(title):
    words = []
    current = []
    for ch in title.lower():
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            current.append(ch)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return "-".join(words)
