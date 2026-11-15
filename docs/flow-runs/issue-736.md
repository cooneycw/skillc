# Flow run record - issue #736

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=62a61995a7a442568ae450309377ec66 -->
## Run 1

- Run-id:            62a61995a7a442568ae450309377ec66
- Run-start:         af08c08fa45b61aa8b88654b52db0c8c796cc965
- Issue:             #736 (PR 1 of 3: the machinery and offline negative controls only)
- Base SHA:          af08c08
- Necessity verdict: Partially addressed (decision 4 is set; the real proof stays blocked on round 1 and on trap tasks, which are PRs 2 and 3)
- Approval:          granted (GO-WITH-CONDITIONS, PR 1 only)
- Approver:          wave orchestrator skillc-orch, wave skillc-work (authority-model orchestrator-only, owner-delegated), mailbox rev 42
- Recorded at:       2026-11-15T13:12:00Z

### Section B evidence
- since 2026-11-14T23:18:58Z: 11acf2a (#720 contracts), 16ce4b1 (#725 round 2), fbe300b (#719 usage) and their fixes; no runner for rounds 3 or 4
- decision 4 is set (issue comment, 2026-11-15): an attempt count; #747 closed as not planned
- dup/super: none (#737 consumes this); host: no sibling touches these paths

### Section C - the approved plan
1. `skillc/gauntlet_trials.py` - the round declaration (skill digest, charter clauses to task dirs, replicates, arms with the named damaged passage, attempt_cap, minimum tasks per clause and minimum held-out size); a seeded train/test split; declared attempts refused with no cap or over it; stop at the cap gives INCOMPLETE; round 3 per-clause pass rates with a separation check via reliability.evaluate_discrimination (UNKNOWN when not shown); round 4 variants scored on held-out with the strict no-worse rule (a declared tolerance is printed); no passing variant gives keep; a ledger keyed by skill digest, task content, grader digest, client and version, model, arm and replicate (a re-run reuses; a changed grader reuses nothing); an AttemptRunner seam with a scripted runner for the controls
2. `skillc/cli.py` - `skillc gauntlet round3|round4 <declaration> [--plan]` under the shared `gauntlet` group (coordinated with skillc-754's `gauntlet run`)
3. `evals/gauntlet-controls` - offline controls: r3 damaged-same gives UNKNOWN; r3 separating passes; r4 a redundant passage gives a passing variant; r4 a lean skill gives keep; no cap or over the cap is refused; stop at the cap gives INCOMPLETE; a re-run gives 0 new; a grader change gives 0 reused; below the minimum tasks gives UNKNOWN; below the minimum held-out gives UNKNOWN
4. `tests/test_gauntlet_trials.py` - each control, plus the split's determinism, the strict rule, and the ledger
5. `skillc/cost_estimate.py` - ruling text only, quoting decision 4
6. `docs/specs/gauntlet-rounds-3-4.md` - the rules, the safe-direction note, and what is not examined
7. `README.md` - the commands
8. `AGENTS.md` - the layout line
9. `changelog.d/736.md` - the fragment

Conditions (rev 42): PR 1 only, with zero model calls; the cache key includes the grader digest and the client version; minimum counts with UNKNOWN; the strict rule with any tolerance printed; the cap controls; the damaged passage named; the gauntlet CLI group shared with #754; cost_estimate ruling text only; targeted set only; up to 3 counter-model passes
Scope: ~9 paths plus control data, ~1,200-1,500 lines. Risks: noisy strict rule (favours keep, the safe direction); too few tasks per clause (UNKNOWN by minimum)

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | not applicable |
| Run placement | will test - Woodpecker CI (full-suite gate); host `make verify` targeted set only; real-Docker runner VM not applicable |
| Execution backend | not covered - PR 1 runs a scripted AttemptRunner; DockerBackend is wired but not exercised until PR 3 |
| Agent client | not applicable - no client runs in PR 1 |
| Client invocation | not applicable |
| Static-check target | not applicable |
| Subject collection | will test - synthetic controls only; CPP not covered (PR 3) |
| Subject installation | not applicable |
| skillc distribution | will test - source checkout (uv sync, editable) via the suite; built wheel in a clean venv not covered |
| Python version | not covered - 3.12 only |

Readers:
- Reader: round 5 (#737) reads the round 3 and 4 verdicts. Compatibility: the verdict vocabulary is fixed in the spec.
- Reader: the owner reads the attempt counts against /usage (decision 4). Compatibility: the report prints attempts, reused and new, and the client and model.

### Reader corrections (counter-model review, pass 1)
- Reader: `Ledger.__init__` reads the persisted JSONL. Compatibility: rows are validated on load (fields, result vocabulary); a malformed line refuses the whole ledger. `test_an_untrustworthy_ledger_row_refuses_the_ledger`.
- Reader: `cmd_gauntlet_round` maps report verdicts to exit codes (0 COMPLETE or PLANNED, 1 REFUSED, 2 a declaration or ledger it cannot read, 3 UNKNOWN or INCOMPLETE). Compatibility: the CLI tests for --plan, the PR-1 refusal and an untrusted ledger.

### Plan deviations
- 2026-11-15, orchestrator mailbox rev 55, at #737's (skillc-754) request and approved: `skillc gauntlet round3|round4 --json` prints `dataclasses.asdict(report)` (`gauntlet_trials.to_json`). It is output-only and additive, with no behaviour change, and it was committed AFTER the counter-model receipt's reviewed head (`9029c4c`). Paths: `skillc/gauntlet_trials.py` (`to_json`), `skillc/cli.py` (the flag), `tests/test_gauntlet_trials.py`, and `tests/fixtures/gauntlet/render-golden.txt`, the text output captured before the change. Tests: JSON equals asdict for a scripted round 3 and round 4, and the text output is unchanged against that golden.
