# cicd project runtime: a warmed project-tools layer (Refs #281)

The cicd runtime (#280: flow-check runtime + curl) plus one task project's
pinned dev tools - ruff, pytest, mypy, the hatchling build backend - and the
grading probe's YAML loader (pyyaml 6.0.3, CPP's own pin), all served offline
from the candidate's uv cache.

```bash
python3 docker/cicd-trial/build.py --base-receipt base.json --receipt cicd.json
python3 docker/cicd-project-trial/build.py --base-receipt cicd.json \
    --project evals/level3/cicd-pipeline/reference --receipt project.json
```

The builder accepts only a `cicd-runtime` receipt, copies just the project's
`pyproject.toml`, `uv.lock` and `src/`, and runs one locked `uv sync` (build-time
network on purpose). It refuses to write a receipt unless the image is the
base plus exactly two layers, keeps the base's user/workdir/env/entrypoint/cmd
and runtime descriptor byte for byte, and a fresh `--network none` container
runs every tool through `uv run --offline --locked` at exactly the versions
the lock pins (and the YAML loader). The receipt (`target`
`cicd-project-runtime`) embeds the cicd receipt whole and binds
`project_lock_sha256` and `tool_versions`; `qualify.py` refuses a receipt whose
lock is not its own `reference/uv.lock`. It is selected by the task, never by a
profile closure.

Nothing is removed or untagged; the layer and its base are tagged
`skillc-cicd-project-runtime:<id12>` / `skillc-cicd-project-base:<id12>`.
Offline controls: `tests/test_level3_cicd_pipeline.py` (fake Docker) and
`tests/test_runtime_supply.py`.
