# Project Makefile - Claude Power Pack Integration
#
# The /flow commands auto-discover these targets:
#   /flow:finish  → runs `make lint` and `make test` (if targets exist)
#   /flow:deploy  → runs `make deploy` (or any target you specify)
#   /flow:doctor  → reports which targets are available
#
# Detected: Python (uv)

.PHONY: lint test typecheck format build deploy clean verify

## Quality gates (used by /flow:finish)

lint:
	uv run ruff check src tests

test:
	uv run pytest -q tests

typecheck:
	_scope=none; for _c in mypy.ini .mypy.ini pyproject.toml setup.cfg; do [ -f "$$_c" ] || continue; _r=$$(awk '/^[[:space:]]*\[/ { s = ($$0 ~ /^[[:space:]]*\[(tool\.)?mypy\][[:space:]]*(#.*)?$$/); if (s) m = 1 } s && /^[[:space:]]*\"?files\"?[[:space:]]*[=:]/ { f = 1 } END { print (m ? (f ? "files" : "nofiles") : "none") }' "$$_c"); [ "$$_r" = none ] && continue; _scope=$$_r; break; done; if [ "$$_scope" = files ]; then uv run mypy; else uv run mypy .; fi

format:
	uv run ruff format .

## Build

build:
	uv build

verify: lint test typecheck
	@echo "All quality gates passed"

## Deployment (used by /flow:deploy)

deploy:
	@echo "Define your deploy steps here"

## Utilities

clean:
	rm -rf .pytest_cache __pycache__ .ruff_cache .mypy_cache dist build *.egg-info .coverage htmlcov

