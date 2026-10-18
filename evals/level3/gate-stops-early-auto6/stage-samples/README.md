# Real pinned-runner finish-plan stdout samples (#287 auto6)

Each `<shape>.stdout` is the stdout of the pinned CPP runner (`tests/fixtures/profile-cpp-codex-flow-auto-86641e8`, CPP `86641e8`) running the **finish** plan. That is the bare invocation `/flow:auto` Step 6 prescribes, on a tree of this task. Captured with:

```bash
cd <tree> && git init -q . && \
  FLOW_GATE_CPP_DIR=<CPP_DIR> bash <CPP_DIR>/scripts/flow-finish-gate.sh
```

`samples.json` names each tree, its exit code and the sha256 of the committed bytes. Two edits only: the absolute snapshot path is replaced by `<CPP_DIR>`, and the capture tree's absolute path (which carried the capturing session's scratch location) by `<TREE>`. `qualify.py` refuses a sample whose bytes no longer match its digest, and feeds each one to a real `GateWitness` whose `flow-finish` gate is read by `skillc.stage_capture.capture_stages(plan="finish")`.

| Sample | Verdict | Exit |
|---|---|---|
| `all-ok` | ok | 0 |
| `all-passed`, `adds-typecheck` | warn (skipped gates: verify) | 3 |
| `typecheck-skipped` | warn (skipped gates: typecheck verify) | 3 |
| `lint-failed`, `test-failed`, `typecheck-failed` | fail | 1 |
