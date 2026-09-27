#!/usr/bin/env bash
# Negative control for the typecheck gate: prove bare `mypy` still reads tests/.
#
# The gate step runs bare `mypy`, whose scope is `[tool.mypy] files` in
# pyproject.toml. #19 was ten type errors in tests/ that nobody saw because the
# gate only checked skillc/, and a scope narrowed back to skillc/ prints the same
# green. So this step plants one type error in a test module of a scratch copy and
# REQUIRES mypy to report it, at that file.
#
# What it does not cover: a gate step rewritten to pass explicit paths
# (`mypy skillc`) bypasses `files` entirely. That is a visible edit to
# .woodpecker/ci.yml, not a silent one, and it is out of this script's reach.
# tests/test_typecheck_control.py holds the committed red cases.
#
# MYPY overrides the command (default `mypy`, so run under `uv run`). It is how
# this script was shown to fail against a stub that always passes.
set -uo pipefail

read -ra MY <<< "${MYPY:-mypy}"
root="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

fail() { echo "typecheck-control: FAIL - $*" >&2; exit 1; }

# The working tree, not `git ls-files`: an untracked test module is still one
# the gate would read. A fixed LIST of `*.py`/`pyproject.toml` files, not a
# directory tree - never `tar -cf - .` over the raw working directory (#20,
# comment 5850673964). Excluding __pycache__/.pytest_cache as tar MEMBERS
# fixed one shape of the race (pipeline 209: a rewritten .pyc reported as
# "file changed as we read it") but not the other: pipeline 140 failed with
# `tar: ./tests: file changed as we read it` on tests/ ITSELF, from pytest
# creating a __pycache__ subdirectory inside it while tar was archiving
# tests/'s own directory listing - excluding a member never touches its
# parent's entry count. mypy only ever reads `*.py` files plus
# `pyproject.toml` (for its own `[tool.mypy]` config) from this copy, so
# `find` builds that exact list up front and tar is never asked to archive
# a directory whose contents a parallel step might change mid-read.
mkdir "$scratch/tree"
file_list="$scratch/files.lst"
( cd "$root" && find . \
    \( -name .git -o -name .venv -o -name .mypy_cache \
       -o -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -prune -o \
    -type f \( -name '*.py' -o -name 'pyproject.toml' \) -print0
) > "$file_list"
[[ -s "$file_list" ]] || fail "found no *.py files to copy"
tar -C "$root" --null -T "$file_list" -cf - \
    | tar -C "$scratch/tree" -xf - || fail "could not copy the tree"

# Derived, not hardcoded: a renamed test module must not silently empty this case.
target="$(cd "$scratch/tree" && find tests -name 'test_*.py' | sort | head -n 1)"
[[ -n "$target" ]] || fail "no tests/test_*.py to plant an error in"

# Baseline: the unmodified copy must pass, so the red below is attributable to
# the planted line and not to a copy that was already broken.
(cd "$scratch/tree" && "${MY[@]}") > "$scratch/baseline.out" 2>&1 \
    || { cat "$scratch/baseline.out" >&2; fail "mypy fails on an unmodified copy"; }

printf '\n_typecheck_control_probe: int = "not an int"\n' >> "$scratch/tree/$target"
line="$(wc -l < "$scratch/tree/$target")"
(cd "$scratch/tree" && "${MY[@]}") > "$scratch/red.out" 2>&1
code=$?
cat "$scratch/red.out"

[[ $code -eq 1 ]] || fail "mypy exited $code with an error planted in $target; expected 1 (is tests/ out of scope?)"
grep -Eq "^$target:$line: error: " "$scratch/red.out" \
    || fail "mypy exited 1 without reporting $target:$line (is tests/ out of scope?)"

echo "typecheck-control: ok - mypy reported the error planted at $target:$line"
