# Flow run record - issue #726

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=ae83b7533bc5404eb80effa142081b0c -->
## Run 1

- Run-id:            ae83b7533bc5404eb80effa142081b0c
- Run-start:         ac3b30c28d248ad1ac54f549bff912c8c1f2959b
- Issue:             #726 (PR A of two: drafting and owner confirmation; PR B, the overlap view, is a later run in its own worktree)
- Base SHA:          ac3b30c (the #746 head, which merges origin/main bca9ea2; #746 is authorized and unmerged)
- Necessity verdict: Still needed
- Approval:          granted (GO-WITH-CONDITIONS)
- Approver:          wave orchestrator skillc-orch, wave skillc-work (authority-model orchestrator-only, owner-delegated), mailbox rev 16
- Recorded at:       2026-11-15T10:55:00Z

### Section B evidence
- commits since 2026-11-14T20:33:20Z: bca9ea2 (#744), 5a79692 (#743), 56bc3e9 (#742), 9ef8d87 (#740), 0665f83 (#734), fbe300b (#735), 16ce4b1 (#733), 48793e1 (#728), 398c477 (#732); none adds charter drafting, confirmation or overlap
- PRs: #744 #743 #742 #740 #735 #734 #733 #732 #728 merged; #746 (#720 format) open and authorized
- dup/super: none (#737 and #725 are sibling rounds; #747 bears on cost)
- host: no sibling worktree with unpushed commits on the charter paths, except this run's base (#746)

### Section C - the approved plan
1. `skillc/charter.py` - evidence assembly (SKILL.md text candidates with file:line quotes under 40 words, git log, usage records), the three columns, UNKNOWN honesty (no log, an empty log, only partial/unsupported coverage), a deterministic observed_as matcher behind a Matcher seam, and a CHARTER.md draft in #720's format with draft clauses and no approved dates
2. `skillc/charter_confirm.py` - applies an owner-written answers file (accept, edit, drop, forbid); refuses with no answers file, an unknown clause or an unanswered clause; stamps approved only on intent and authority clauses
3. `skillc/cost_estimate.py` - round-1 model-run sizing (calls x replicates x tokens), labelled sized, not run; never authorizes
4. `skillc/cli.py` - `charter draft` and `charter confirm` (nothing to draft from exits non-zero; refuses to overwrite an existing CHARTER.md)
5. `evals/subjects/charter-draft` - drafting control fixtures: stated-unseen, observed-unstated, and each UNKNOWN trigger plus the full-coverage flip case
6. `tests/test_charter.py` - columns, the UNKNOWN triggers and the flip, nothing to draft from, overwrite refusal; a draft passes contract-shape, warns approval-present, and fails clause-backed (asserted as expected)
7. `tests/test_charter_confirm.py` - no answers file refused; accept-all stamps approved only on intent and authority, asserting no other clause carries approved; unknown or missing answers refused; forbid yields a never clause
8. `tests/test_readme_drift.py` - the charter command
9. `docs/specs/charter-round1.md` - columns, UNKNOWN rules, the answers format, the dialogue prompt in the grilling style, the cost sizing, and what is not examined
10. `docs/measurements/round1` - deterministic drafts of CPP flow-eli5 and flow-auto at a pinned CPP SHA, each ending "draft ready for owner confirmation"; quotes under 40 words with cites
11. `README.md` - the charter command
12. `AGENTS.md` - layout lines
13. `changelog.d/726.md` - fragment

Conditions (orchestrator rev 16): two PRs, B stacked on A; separate UNKNOWN control per trigger plus the flip case; committed no-self-approval negative case; no paid or subscription model calls, sizing labelled "sized, not run"; local model only after PR B merges, never writing a CHARTER.md; proof drafts in skillc, CPP SHA pinned, CHARTER.md placement named as an owner question; clause-backed failure asserted; push only after SILENT PERIOD resume and #746's merge; 3-pass counter-model ceiling per PR
Scope: ~13 paths plus fixture files, ~1,000-1,200 lines. Risks: crude deterministic extraction undercounts stated duties; observed_as is an unadopted convention so the observed column is mostly UNKNOWN; stacked on unmerged #746

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | will test - usage logs resolve through usage.discover_logs, main checkout and linked worktree |
| Run placement | will test - CI and host `make verify` only |
| Execution backend | not applicable - no trial runs |
| Agent client | not applicable - no client runs, no model calls |
| Client invocation | not applicable - no client runs |
| Static-check target | not applicable - no new static rule |
| Subject collection | will test - synthetic fixtures, plus CPP at a pinned SHA for the two proof drafts |
| Subject installation | not applicable - nothing installed |
| skillc distribution | will test - source checkout (uv sync, editable) via the suite, and built wheel in a clean venv via `make clean-install` |
| Python version | not covered - 3.12 only, unchanged |

### Plan deviations
- 2026-11-15, orchestrator mailbox rev 18, recording the owner's decision on charter location (claude-power-pack#1838): a slash command's charter lives at `charters/<ns>/<cmd>/CHARTER.md` at the collection root, with a required `subject:` naming the command file; a native skill keeps CHARTER.md beside SKILL.md; never in a generated mirror. Added to PR A, outside the Section C list:
  - `skillc/contracts.py` - `subject` becomes a known field. It is required under `charters/`, optional beside a SKILL.md but must then name that SKILL.md, and a subject that does not exist fails contract-shape with a named reason. Discovery already walks `charters/**`. contract-shape is reused rather than adding a new rule, so selftest stays at 48.
  - `controls/contract-shape` - bad/subject-missing, bad/subject-dangling, good/subject-command
  - `tests/test_contracts.py` - subject rules
  - `docs/specs/contracts.md` - the `subject` field and the charters/ layout
  - effect on the outcome: the CPP proof drafts use `charters/flow/{eli5,auto}/CHARTER.md` with a subject naming `.claude/commands/flow/*.md`, drafted from the command file, never the codex mirror

### Lane and reader corrections (counter-model review, pass 1)
The pass-1 review found three lane answers that claimed more than this change tests. Corrected:
- Checkout: **not covered**. `charter draft --usage` takes explicit paths and `discover_logs` scans what it is given. Nothing here resolves a main checkout from a linked worktree, so neither layout is tested by this change.
- Subject collection: synthetic fixtures **will test** (`evals/subjects/charter-draft`). CPP at `3ed2546` is **not covered** in CI: the proof drafts were produced by hand and re-checked by hand in a CPP-layout copy, as recorded in `docs/measurements/round1/README.md`.
- skillc distribution: source checkout **will test** (the suite). Built wheel **not covered** for the new commands: `make clean-install` exercises selftest and check, not `charter`.

Readers of the changed output:
- Reader: `charter_confirm.confirm` reads `charter draft` YAML. Compatibility: the emitter round-trip test, and confirm tests built on real drafts.
- Reader: `contracts.load` and the nine contract rules read drafts and confirmed charters, including `subject`, `draft` and `approved`. Compatibility: `test_a_draft_passes_contract_shape_warns_approval_and_fails_clause_backed` and `test_a_command_draft_carries_its_subject_and_passes_shape`.
- Reader: `decay.copied_passage` (`skillc inspect`) reads reports that hold quotes. Compatibility: `test_a_quote_never_trips_the_copied_passage_detector`, which runs the real detector.
- Reader: the owner, who reads drafts and the round-1 README. Compatibility: none mechanical; this is the confirmation dialogue.
