# Stdlib-only targets in CPP's python-uv.mk shape: every target runs through
# `uv run` against a project with no dependencies, so it works offline.
.PHONY: lint test typecheck format build deploy clean verify

lint:
	uv run python3 -m py_compile src/calc/__init__.py tests/check_calc.py

test:
	PYTHONPATH=src uv run python3 -m unittest discover -s tests -p "check_*.py" -v

typecheck:
	uv run python3 -m compileall -q src

format:
	@echo "format: no formatter in the offline stdlib toolchain"

build:
	mkdir -p dist && tar -cf dist/calc.tar src

deploy: verify
	@echo "deploy: local only - no remote target"

clean:
	rm -rf dist .venv src/calc/__pycache__ tests/__pycache__

verify: lint test typecheck
