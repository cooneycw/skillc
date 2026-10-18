# Contributing

- Every fix ships with a regression test under `tests/` that fails on the
  code before the fix and passes after it.
- `make check` is the gate. It runs lint, the test suite and typecheck, in
  that order, and must pass before a change ships.
- Close the issue your fix resolves in your commit message.
