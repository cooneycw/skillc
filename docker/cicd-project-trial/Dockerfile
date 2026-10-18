# cicd project runtime (skillc#281): the validated cicd runtime image plus a
# warmed uv cache for ONE task project's pinned dev tools (ruff, pytest, mypy
# and the hatchling build backend), so the task's generated `uv run` targets
# work with no network. build.py binds the result: the base's layers plus
# exactly these two, the base's user/workdir/env/entrypoint/cmd, the base's
# runtime descriptor byte for byte, and an offline smoke run of every tool.
ARG BASE
FROM ${BASE}
# The project's pyproject.toml, uv.lock and package skeleton - the lock is what
# the receipt binds; nothing here is the candidate's code.
COPY --chown=candidate:candidate warm/ /tmp/skillc-cicd-project-warm/
# Build-time network is intentional (the runtime's own UV_OFFLINE=1 is lifted
# for this one command); `--locked` refuses any lock drift.
# The grading probe parses the generated YAML with pyyaml 6.0.3, the version
# CPP's own lock pins for its pipeline generator; resolving it once here caches
# what an offline `uv run --with` needs.
RUN cd /tmp/skillc-cicd-project-warm \
    && UV_OFFLINE=0 uv sync --locked \
    && UV_OFFLINE=0 uv run --no-project --with pyyaml==6.0.3 python -c "import yaml" \
    && rm -rf /tmp/skillc-cicd-project-warm
