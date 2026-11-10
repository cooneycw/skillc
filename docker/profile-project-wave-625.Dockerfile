# Public committed source only. The proof installs into a new container-local home.
FROM python@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a
RUN apt-get update -qq && apt-get install -y --no-install-recommends bash git jq procps util-linux && rm -rf /var/lib/apt/lists/*
COPY skillc /opt/controller/skillc
COPY tests /opt/controller/tests
COPY evals /opt/controller/evals
ENV PYTHONPATH=/opt/controller:/opt/controller/tests PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
ENTRYPOINT ["python3", "/opt/controller/tests/profile_project_wave_cold.py", "/proof/home"]
