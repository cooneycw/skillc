# Lanes demonstrated - issue #760 (PR 2 of 2)

<!-- lanes-demonstrated run=5608388be35747b9aa8fe7556e5ff254 plan=092e4cc3165e615c1ee18dd36784cc8b0e77cf152fd7ae5bc038c081190d2540 -->

| Lane | Result | Evidence |
|---|---|---|
| Checkout | passed - main checkout | every engine test runs on a fresh git collection; linked worktree: not tested |
| Run placement | passed - host targeted set; Woodpecker CI on the PR is the gate | tests/test_gauntlet.py, test_gauntlet_report.py, test_gauntlet_verdict.py, test_charter.py, test_usage.py |
| Subject collection | passed - synthetic (evals/subjects/gauntlet; its usage log gains alpha's invocation); CPP at d5ef0a66: the pinned test passes unchanged | |
| skillc distribution | passed - source checkout; built wheel: not tested | |
| Python version | passed - 3.12; 3.11 not tested | |
| Reader: round 0 reading `usage report` text | passed | the real command on the fixture logs; a renamed heading reads UNKNOWN |
| Reader: round 1's key reading declared tests via contracts.load | passed | a deleted declared test, a dangling declared link, a charter under .venv/.git/.skillc/gauntlet each re-run round 1; `/` is never walked |
| Reader: the plain report reading the new reasons | passed | skill-not-in-log wording test; plain goldens regenerated for round 0's count, machine goldens byte-identical |
| Reader: the engine's resume (`_cached`) reading the expanded inputs | passed | it compares the whole inputs dict, so each new key invalidates; the "(cached)" controls show unchanged inputs still reuse |
| Reader: gauntlet_verdict `_stale_round` reading recorded inputs | passed, with a known gap | it reads only skill/charter/collection, so the new keys neither break it nor are consulted; gauntlet_verdict tests pass unchanged; the gap is in the Nit Store (#20) |
