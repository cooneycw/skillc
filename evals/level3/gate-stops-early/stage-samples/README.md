# Real pinned-runner stdout samples (#376)

Each `<shape>.stdout` is the stdout of the pinned CPP runner
(`tests/fixtures/profile-cpp-codex-flow-check-ea6dbfa`) on a tree of this
task, captured with:

```bash
cd <tree> && git init -q . && \
  FLOW_GATE_CPP_DIR=<CPP_DIR> bash <CPP_DIR>/scripts/flow-finish-gate.sh --plan check --evidence flow-check
```

`samples.json` names the tree, the exit code and the sha256 of the committed
bytes. The only edit is the absolute snapshot path, replaced by `<CPP_DIR>`.
`qualify.py` refuses a sample whose bytes no longer match its digest, and
feeds each to a real `GateWitness` whose `flow-check-plan` gate is read by
`skillc.stage_capture.capture_stages`. `tests/test_stage_capture.py` checks
the reader's outcome for every sample.
