# merge-admission controls (Kyle #2130, ADR 0011 D3)

Committed cases for `ci/merge_admission.py`, read by `tests/test_merge_admission.py`.

- `good/ci.yml`: an ordinary pipeline. It names `kyle-lock acquire main-merge`
  only in comments, inline and inside the script it runs. That proves a mention
  is not a finding, so the gate cannot be satisfied or tripped by grepping.
- `bad/ci.yml`: a pipeline whose only route to `main-merge` is a repository
  script it runs (`scripts/merge-lock.sh`). The merger holds `main-merge` while
  it waits for this pipeline, so this is the D3 deadlock.
- `good/transcript.json` / `bad/transcript.json`: a coordinated merger's
  ordered external calls, and the uncoordinated `gh pr merge` that preceded it.
- `blind/merge_admission_blind.py`: a FROZEN copy of the pipeline check with
  script-following removed. It must MISS `bad/ci.yml`, which shows the bad
  case exercises the feature that catches it rather than an inline literal any
  scan would see. Do not update it to match the gate.

The pipelines' commands are harmless (`echo`, `true`). The D3 test executes them
under a recording fake `kyle-lock` while a merger holds the lease.
