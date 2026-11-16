# Gauntlet rounds 3 and 4: offline controls (#736, PR 1)

One skill (`skill/SKILL.md`, three named passages), six trap-task stubs (two
clauses with three tasks each) and one declaration (`declaration.json`).
`tests/test_gauntlet_trials.py` runs every control through `ScriptedRunner`:
no model is called, and the task stubs are never read by an agent.

| control | scripted outcome | the round must read |
|---|---|---|
| round 3 separating | `damaged-gate` fails its clause's tasks | COMPLETE |
| round 3 damaged-same | `damaged-gate` passes like the intact skill | UNKNOWN |
| round 4 redundant passage | `lean-repeat` passes everything | trim (`lean-repeat` passes) |
| round 4 lean skill | every variant is worse on some clause | keep |
| no cap / over the cap | - | REFUSED, 0 runner calls |
| `partial: true` under a small cap | - | INCOMPLETE, exactly `cap` calls |
| re-run | - | 0 new attempts |
| grader changed | - | 0 reused attempts |
| below min tasks / min held-out | - | UNKNOWN |

These control the machinery only. Whether a real task set separates a real
damaged skill is what the real run (#736 PR 3) measures.
