# Gate expectations: the pinned CPP finish gate on this task's fixtures

The verbatim marker lines the REAL pinned gate (`claude-power-pack` 86641e8,
`scripts/flow-finish-gate.sh`, run bare in the repository, with uv on PATH) prints on three trees.
They are measured, not authored. `tests/test_flow_auto_necessity_task.py` compares them to a live
run when the gate's closure is available, and skips loudly otherwise.

| File | Tree | Verdict |
|---|---|---|
| `old.tail` | grader revision 1's fixture (no Makefile) | exit 3, `warn (skipped gates: lint test typecheck verify)`: nothing ran |
| `new.tail` | revision 2's CLEAN fixture | exit 0, `ok`, with lint/test/typecheck subsumed under `make verify` |
| `broken.tail` | revision 2's CLEAN fixture with one test assertion deliberately broken (a test-only tree, not a candidate) | exit 1, `fail (at prerequisite test)` |

`old.tail` is the regression control: a future fixture that loses its gate surface warns again.
`broken.tail` is the negative control: the gate surface can say no.
