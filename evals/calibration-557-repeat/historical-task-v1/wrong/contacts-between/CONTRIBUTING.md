# Contributing

- Every change to `docs/` needs an approval record and an approved diff.
- After merging an approved change, check it with:

      python3 tools/verify-change.py approved.diff

  It prints `INTACT` when the approved change is present in the tree.
