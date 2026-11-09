def step(since, now, load):
    since = (now if since is None else since) if load >= 20 else None
    return since, since is not None and now - since >= 119
