

def _swallow() -> None:
    try:
        pass
    except:  # noqa: E722, S110 - the planted lint failure this candidate exists for
        pass
