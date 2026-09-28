def count_words(text: str) -> int:
    """Count words in `text`. Buggy: splits on a single space, so runs of
    whitespace or leading/trailing space inflate the count."""
    return len(text.split(" "))
