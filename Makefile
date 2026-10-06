# Minimal Makefile (#134 item 2) so a local gate exists at all: without one,
# CPP's finish gate had nothing to fall back to and silently skipped
# `skillc selftest` and `ci/negative-control.sh` - a change that blinds one
# rule's control went green locally and red only in CI (#37 was exactly
# this). `verify`'s prerequisites cover every step .woodpecker/ci.yml runs -
# tests/test_ci_local_gate_coverage.py fails when a new CI step has no
# target here. AGENTS.md's `## Verify` section is the authoritative
# description, keep both in sync.
#
# Cross-model review on PR #156, after #155 went red on changelog-check
# (pipeline 329): the first version of this file mirrored only `gate` and
# `negative-control`, so a PR could pass `make verify` and still go red on
# any of the other five steps.
#
# Bash with pipefail, not the default POSIX sh: `test`'s `pytest | tee` must
# fail the target (and so `verify`) on a real pytest failure, not on tee's
# own near-always-zero exit.
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

.PHONY: sync selftest test lint typecheck negative-control typecheck-control \
	leak-check changelog-check readme-drift secret-scan git-tests-control verify

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
	uv run --no-sync pytest -rA --junit-xml=reports/pytest-report.xml $(PYTEST_ARGS) | tee reports/pytest.log

lint: sync
	uv run --no-sync ruff check .

typecheck: sync
	uv run --no-sync mypy

negative-control: sync
	uv run --no-sync bash ci/negative-control.sh

typecheck-control: sync
	uv run --no-sync bash ci/typecheck-control.sh

# .woodpecker/ci.yml's leak-check step's SKILLC_EXCLUDE_ARGS, plus ONE
# LOCAL-ONLY addition: `reports/` (`test`'s own -rA output, gitignored, never
# part of the reviewed tree) is not excluded there, because CI's leak-check
# step runs in its own checkout and never has a reports/ directory to see -
# only `verify`'s own `test` target, run first in the SAME tree, creates it.
# Without this, `make verify` fails on ITS OWN prior output: reports/pytest.log
# captures -rA's per-test detail, including the seeded fake-leak literals
# controls/leak-check/bad and tests/test_leak.py's own fixtures assert
# against - real findings, correctly reported, about a file that was never
# going to be committed. Measured: `make verify` failed
# on exactly this the first time leak-check was chained after test.
SKILLC_LEAK_EXCLUDE := --exclude controls/leak-check/bad --exclude tests/test_leak.py \
	--exclude ci/leak-check-control.sh --exclude tests/fixtures/leak_seeds --exclude reports
leak-check: sync
	uv run --no-sync skillc leak-check . $(SKILLC_LEAK_EXCLUDE)
	uv run --no-sync bash ci/leak-check-control.sh

# Needs origin/main fetched, unlike CI's own step (a fresh shallow clone
# there vs. a worktree here that may be stale) - fails clearly rather than
# comparing against a stale local origin/main if the fetch itself fails.
changelog-check:
	git fetch origin main --quiet
	python3 ci/changelog_check.py origin/main

readme-drift: sync
	uv run --no-sync python3 ci/readme_drift.py

# CI always runs gitleaks (its own pinned image carries it); a dev machine
# may not have it installed. Skip loudly rather than pass silently - a
# missing scanner is not evidence of no secret.
secret-scan:
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks dir . --config .gitleaks.toml --redact --no-banner && bash ci/secret-scan-control.sh; \
	else \
		echo "secret-scan: SKIPPED - gitleaks is not installed locally (CI always runs it)"; \
	fi

# #307: `test`'s --junit-xml=reports/pytest-report.xml is this target's
# input - depends on `test` directly (not merely listed after it in `verify`)
# so `make git-tests-control` alone, without a prior `make test`, fails on a
# missing report rather than silently reading a stale one from an earlier run.
git-tests-control: test
	python3 ci/check_git_tests_ran.py reports/pytest-report.xml
	bash ci/git-tests-control.sh

verify: selftest test lint typecheck negative-control typecheck-control leak-check \
	changelog-check readme-drift secret-scan git-tests-control
