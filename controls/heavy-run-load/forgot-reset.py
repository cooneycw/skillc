def step(since, now, load):
    since = now if since is None else since
    return since, since is not None and now - since >= 120
