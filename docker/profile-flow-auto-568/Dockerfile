# Public controller/source context only; no installed home or operator state.
FROM python@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS base
COPY --from=ghcr.io/astral-sh/uv@sha256:68d029b921923c7234ef0178e669d6d253c8356153f1b54316df8cc3e15f5c01 /uv /uvx /usr/local/bin/
RUN apt-get update -qq && apt-get install -y --no-install-recommends git make bash && rm -rf /var/lib/apt/lists/*
COPY skillc /opt/controller/skillc
COPY tests /opt/controller/tests
COPY evals /opt/controller/evals
ENV PYTHONPATH=/opt/controller:/opt/controller/tests PYTHONDONTWRITEBYTECODE=1
FROM base AS cached
RUN cd /opt/controller/tests/fixtures/profile-cpp-codex-flow-auto-87ecb097 && UV_CACHE_DIR=/opt/cache uv sync --locked --no-install-project && sha256sum uv.lock | cut -d' ' -f1 > /opt/cache-lock.sha256
FROM base AS uncached
# Purpose-explicit empty cache twin; callers MUST specify --target.
