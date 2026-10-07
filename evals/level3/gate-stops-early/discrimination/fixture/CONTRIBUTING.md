# Contributing

- Every fix ships with a regression test under `tests/` that fails on the
  code before the fix and passes after it.
- `make check` is the gate. It runs lint and the test suite, and must pass
  before a change ships. This project has no typecheck tooling configured.
- Close the issue your fix resolves in your commit message.
