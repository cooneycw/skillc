def count_words(text: str) -> int:
    """Count words in `text`, ignoring any run of whitespace."""
    return len(text.split())
