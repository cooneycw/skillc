# Minimal Makefile (#134 item 2) so a local gate exists at all: without one,
# CPP's finish gate had nothing to fall back to and silently skipped
# `skillc selftest` and `ci/negative-control.sh` - a change that blinds one
# rule's control went green locally and red only in CI (#37 was exactly
# this). `verify`'s prerequisites mirror Woodpecker's `gate` step order
# (.woodpecker/ci.yml) plus its separate `negative-control` step; AGENTS.md's
# `## Verify` section is the authoritative description, keep both in sync.
#
# Bash with pipefail, not the default POSIX sh: `test`'s `pytest | tee` must
# fail the target (and so `verify`) on a real pytest failure, not on tee's
# own near-always-zero exit.
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

.PHONY: sync selftest test lint typecheck negative-control verify

sync:
	uv sync --locked --extra dev

selftest: sync
	uv run --no-sync skillc selftest

# -rA (#148): every outcome survives even when the run as a whole passes.
# Also teed to a gitignored log: #148's second sighting (flow:auto #12's
# flaky test) was a LOCAL failure after `uv sync`, never captured - the CI
# gate's own -rA does not help a run that never reaches CI.
#
# PYTEST_ARGS narrows what runs (used by
# tests/test_makefile_pipefail_control.py's negative control, and by anyone
# who wants a faster local loop); empty by default, so plain `make test`
# still runs the whole suite.
PYTEST_ARGS ?=
test: sync
	mkdir -p reports
	uv run --no-sync pytest -rA $(PYTEST_ARGS) | tee reports/pytest.log

lint: sync
	uv run --no-sync ruff check .

typecheck: sync
	uv run --no-sync mypy

negative-control: sync
	uv run --no-sync bash ci/negative-control.sh

verify: selftest test lint typecheck negative-control
