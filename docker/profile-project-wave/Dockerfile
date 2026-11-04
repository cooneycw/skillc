# Exact public source only. Operator homes, credentials and source checkouts
# are never bind-mounted into this model-free cold command proof.
FROM python@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a
COPY --from=ghcr.io/astral-sh/uv@sha256:68d029b921923c7234ef0178e669d6d253c8356153f1b54316df8cc3e15f5c01 /uv /uvx /usr/local/bin/
RUN apt-get update -qq && apt-get install -y --no-install-recommends git make bash jq procps && rm -rf /var/lib/apt/lists/*
# Existing shared cold-budget support imports pytest. Match skillc's lock.
RUN python -m pip install --no-cache-dir pytest==9.1.1
COPY skillc /opt/controller/skillc
COPY tests /opt/controller/tests
COPY evals /opt/controller/evals
COPY controls /opt/controller/controls
COPY docker/fixture-service/skillc-gh-shim.py /opt/controller/gh-shim.py
# The real engine calls uv sync. Warm its exact scaffold inside the image;
# the runtime actor receives only this cache and runs with network none.
RUN UV_CACHE_DIR=/opt/scaffold-cache GIT_AUTHOR_NAME=Fixture GIT_AUTHOR_EMAIL=fixture@example.invalid GIT_COMMITTER_NAME=Fixture GIT_COMMITTER_EMAIL=fixture@example.invalid python /opt/controller/tests/fixtures/profile-cpp-codex-project-wave-auto-87ecb097/scripts/project-init.py --project-name widget --framework python --target-dir /opt/scaffold-warm
ENV PYTHONPATH=/opt/controller:/opt/controller/tests UV_OFFLINE=1
