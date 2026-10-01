# Contributing

- Every fix ships with a regression test under `tests/` that fails on the
  code before the fix and passes after it.
- `make check` is the gate. It must pass before a change ships. `make check`
  runs `ci/check.py`.
- Close the issue your fix resolves in your commit message.
