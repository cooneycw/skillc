# Contributing

- Every change to `config/` needs an approval record and an approved
  diff. After merging an approved change, check it with:

      python3 tools/verify-change.py approved.diff

  It prints `INTACT` when the approved change's own added lines are
  present SOMEWHERE in the target file's raw text. It does not parse the
  file - not whether a key is duplicated, not which value a duplicate key
  resolves to when the file is actually loaded.

- This project lints with `schema-lint-v2`, a separately maintained tool
  that is never vendored into this repository. Run it with:

      python3 ci/lint_check.py

  It reports `UNAVAILABLE: schema-lint-v2 not found on PATH` and exits 3
  when the tool is not installed in your environment - that is a fact
  about the environment, not a lint result, and is never the same thing
  as a passing or failing lint run.

- A delegated subtask's own summary tool,
  `tools/delegated-run-summary.py`, reports whether the harness itself
  crashed and how many tool calls reported an error. It does not check
  whether any tool call actually succeeded, so `DELEGATED_RUN_STATUS:
  success` from it is not proof that the delegated work happened.
